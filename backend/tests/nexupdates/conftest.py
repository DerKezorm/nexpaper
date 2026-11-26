"""Loads the app's adapter (``backend/tests/nexupdates_adapter.py``, or the file named by ``NEXUPDATES_ADAPTER``) and
gives every contract test a fresh app with the stand-in for GitHub in place of the network. Copied unchanged into
every app."""

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
contract = importlib.import_module("updates_contract")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXUPDATES_ADAPTER") or HERE.parent / "nexupdates_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexupdates_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexupdates_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _adapter_module()


@pytest.fixture
def github() -> Iterator[Any]:
    fake = contract.FakeGitHub()
    yield fake
    fake.close()


@pytest.fixture
def app(github: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    # A proxy in the environment must not matter (the module ignores it); one that refuses makes sure.
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "")
    adapter = ADAPTER.Adapter()
    adapter.start()
    try:
        contract.plug(adapter, github)
        yield adapter
    finally:
        contract.contract_package(adapter).forget()
        adapter.stop()


@pytest.fixture
def nexupdates(app: Any) -> ModuleType:
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
