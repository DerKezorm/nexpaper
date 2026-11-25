"""Loads the app's adapter (``backend/tests/nexkonten_adapter.py``, or the file named by ``NEXKONTEN_ADAPTER``) and
gives every contract test a fresh app and the vendored package. Copied unchanged into every app."""

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
contract = importlib.import_module("konten_contract")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXKONTEN_ADAPTER") or HERE.parent / "nexkonten_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexkonten_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexkonten_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _adapter_module()


@pytest.fixture
def app() -> Iterator[Any]:
    adapter = ADAPTER.Adapter()
    adapter.start()
    package = contract.konten_package(adapter)
    package.setup.forget_generated_code()
    # What lives in memory: an enrolment, a waiting sign-in, a challenge, the brake.
    package.factor.forget()
    package.passkeys.forget()
    package.brake.BRAKE.forget()
    try:
        yield adapter
    finally:
        package.use_transport(None)
        adapter.stop()


@pytest.fixture
def konten(app: Any) -> ModuleType:
    return contract.konten_package(app)


@pytest.fixture
def operator(app: Any) -> tuple[Any, str]:
    """The first operator, with a password: (id, password)."""
    secret = contract.password()
    account_id = app.seed("boss", display_name="Boss", email="boss@example.com", password=secret, operator=True)
    return account_id, secret
