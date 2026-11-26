"""Loads the app's adapter (``backend/tests/nexsprachen_adapter.py``, or the file named by ``NEXSPRACHEN_ADAPTER``)
and gives every contract test a fresh app and the vendored package. Copied unchanged into every app."""

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
contract = importlib.import_module("sprachen_contract")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXSPRACHEN_ADAPTER") or HERE.parent / "nexsprachen_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexsprachen_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexsprachen_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _adapter_module()


@pytest.fixture
def app() -> Iterator[Any]:
    adapter = ADAPTER.Adapter()
    adapter.start()
    try:
        contract.contract_package(adapter).forget()
        yield adapter
    finally:
        adapter.stop()


@pytest.fixture
def nexsprachen(app: Any) -> ModuleType:
    return contract.contract_package(app)


@pytest.fixture
def operator(app: Any) -> Any:
    return app.client("operator")


@pytest.fixture
def member(app: Any) -> Any:
    return app.client("member")


@pytest.fixture
def anonymous(app: Any) -> Any:
    return app.client("anonymous")


@pytest.fixture
def reader(app: Any, member: Any, anonymous: Any) -> Any:
    """Who reads in this app: anybody when it reads without signing in, else a signed-in member."""
    return anonymous if app.public_read else member


@pytest.fixture
def folder(app: Any) -> Path:
    return app.folder()
