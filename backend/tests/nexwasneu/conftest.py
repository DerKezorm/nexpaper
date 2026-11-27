"""Loads the app's adapter (``backend/tests/nexwasneu_adapter.py``, or the file named by ``NEXWASNEU_ADAPTER``) and
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

# Imported by name after the path is set: a plain import statement here would sit below code.
contract = importlib.import_module("wasneu_contract")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXWASNEU_ADAPTER") or HERE.parent / "nexwasneu_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexwasneu_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexwasneu_adapter"] = module
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
        contract.contract_package(adapter).forget()
        adapter.stop()


@pytest.fixture
def nexwasneu(app: Any) -> ModuleType:
    return contract.contract_package(app)


@pytest.fixture
def swapped(app: Any, tmp_path: Path) -> Iterator[ModuleType]:
    """The app with the contract's texts and 2.3.0 as the running version."""
    with contract.swapped(app, tmp_path / "texts") as package:
        yield package


@pytest.fixture
def operator(app: Any) -> Any:
    return app.client("operator")


@pytest.fixture
def member(app: Any) -> Any:
    return app.client("member")


@pytest.fixture
def anonymous(app: Any) -> Any:
    return app.client("anonymous")
